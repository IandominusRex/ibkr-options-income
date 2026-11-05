"use client";

import clsx from "clsx";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { Card } from "@/components/ui/Card";
import { Disclosure } from "@/components/ui/Disclosure";
import { Meter } from "@/components/ui/Meter";
import { StatusWord } from "@/components/ui/StatusWord";
import { Stub, formatStubValue, type StubLineData } from "@/components/ui/Stub";
import { apiFetch } from "@/lib/api";
import { UNKNOWN } from "@/lib/format";
import { formatMoneyCell } from "@/lib/money";
import type { StrategyFilter } from "@/lib/strategy";
import type { MonthPay, MonthPayResponse } from "./types";

const MONTH = new Intl.DateTimeFormat("en-US", { month: "long", timeZone: "UTC" });

/** The value book's own stub: what it sold, the commissions we know of (none are recorded) and the net. */
function valueStubLines(pay: MonthPay, unknown: boolean): StubLineData[] {
  const vc = pay.value_commissions ?? null;
  const fees: StubLineData =
    pay.value_commissions_complete === false
      ? vc === null
        ? {
            label: "Commissions (not recorded)",
            value: null,
            format: "signed-money",
            explain: "The value book's store holds no commission, so the net below is before them.",
          }
        : { label: "Commissions (incomplete)", value: unknown ? null : -vc, format: "signed-money" }
      : { label: "Commissions", value: unknown ? null : -(vc ?? 0), format: "signed-money" };
  return [
    {
      label: "Value book, realised",
      value: unknown ? null : (pay.value_realised ?? 0),
      format: "signed-money",
      explain: "Shares sold from the value book this month: the proceeds less the average cost of what was sold.",
    },
    fees,
    { label: "Net so far", value: unknown ? null : pay.net, format: "signed-money", total: true },
  ];
}

/**
 * `unknown` blanks every figure: a month whose only income source could not be read. Under All the
 * value book's realised result is its own line beneath the net, never part of it: a share sale is a
 * capital gain and the target is the wheel's wage (plan ruling 26).
 */
export function payStubLines(pay: MonthPay, unknown = false): StubLineData[] {
  if (pay.strategy === "value") return valueStubLines(pay, unknown);
  const lines: StubLineData[] = [
    {
      label: "Premium collected",
      value: unknown ? null : pay.premium_collected,
      format: "signed-money",
      explain: `Credit from ${pay.n_opened} position${pay.n_opened === 1 ? "" : "s"} sold this month.`,
    },
    {
      label: "Bought back",
      value: unknown ? null : -pay.bought_back,
      format: "signed-money",
      explain: `What it cost to close ${pay.n_closed} position${pay.n_closed === 1 ? "" : "s"} this month.`,
    },
    {
      label: pay.commissions_complete ? "Commissions" : "Commissions (incomplete)",
      value: unknown ? null : -pay.commissions,
      format: "signed-money",
      explain: pay.commissions_complete
        ? "IBKR commissions on every fill that touched this month."
        : "Some fills have no commission recorded yet, so this is a lower bound.",
    },
    { label: "Net so far", value: unknown ? null : pay.net, format: "signed-money", total: true },
  ];
  return lines;
}

/**
 * Under All, the value book's realised result as a stub of its own beneath the pay stub, so it can
 * never read as one more line of the sum above it. Null when the book sold nothing this month.
 */
export function valueBesideLines(pay: MonthPay, unknown = false): StubLineData[] | null {
  if (unknown || pay.strategy === "value" || pay.value_realised == null) return null;
  return [
    {
      label: "Value book, realised",
      value: pay.value_realised,
      format: "signed-money",
      explain:
        "Shares sold from the value book this month. A share sale is a capital gain, so it sits beside the net and is not added to it or to the target.",
    },
  ];
}

export function PayCard({ strategy }: { strategy: StrategyFilter }) {
  const { data, isError } = useQuery({
    queryKey: ["pnl", "month", strategy],
    queryFn: () => apiFetch<MonthPayResponse>(`/pnl/month?strategy=${strategy}`),
    refetchInterval: 60_000,
  });

  if (isError && !data) {
    return (
      <Card className="mt-4">
        <p className="text-sm text-muted">Could not load this month's pay.</p>
        <p className="mt-1 text-[0.8125rem] text-muted">It tries again every minute.</p>
      </Card>
    );
  }
  if (!data) {
    return (
      <Card as="div" className="mt-4 h-[104px]" role="status" aria-busy="true" aria-label="Loading this month's pay" />
    );
  }

  const pay = data.pay;
  const month = MONTH.format(new Date(pay.month));
  // A spreads book is in scope but data/spreads.db could not be read. Never show the wheel's
  // total as the whole month, and never show an unread spreads-only month as $0.
  const spreadsOut = data.spreads_available === false && (pay.strategy === "all" || pay.strategy === "spread");
  const isValue = pay.strategy === "value";
  // The same rule for the value book: an unread book is not a month of $0, and under All it is
  // flagged without hiding the options income.
  const valueOut = data.value_available === false && (pay.strategy === "all" || isValue);
  const wholeUnknown = (spreadsOut && pay.strategy === "spread") || (valueOut && isValue);
  const beside = valueBesideLines(pay, wholeUnknown);
  const net = wholeUnknown ? null : pay.net;
  // An unread spread-only month keeps its target (it comes from the account value, not the
  // spreads book); only the progress against it is unknown.
  const progress = wholeUnknown ? null : pay.progress_pct;
  const daysLeft = `${pay.days_left} ${pay.days_left === 1 ? "day" : "days"} left`;
  const noTarget = pay.target_mode === "off" && !isValue;
  const pace = isValue ? (
    "The income target counts options income only."
  ) : noTarget ? (
      `No target set · ${daysLeft}`
    ) : pay.target === null ? (
      // The setting is there; the account value at the month's start is not (the first month
      // after install, or a journal gap), so the target cannot be worked out.
      <>
        Target <span className="hatch">{UNKNOWN}</span> · needs the month's opening account value · {daysLeft}
      </>
    ) : progress === null ? (
      <>
        <span className="hatch">{UNKNOWN}</span> of target · {daysLeft}
      </>
    ) : (
      `${Math.round(Math.max(0, progress))}% of target · ${daysLeft}`
    );

  return (
    <Card className="mt-4">
      <Disclosure
        tone="plain"
        summary={
          <span className="block">
            {/* Each phrase is unbreakable: the figure block drops below the title when they do not
                fit side by side (320px), and "of $target" drops under the net as one unit. */}
            <span className="flex flex-wrap items-baseline justify-between gap-x-2.5">
              <span className="whitespace-nowrap text-[1.0625rem] font-bold">
                {month} {isValue ? "value book" : "pay"}
              </span>
              <span className="tabular ml-auto text-right font-mono font-semibold">
                <span className={clsx("whitespace-nowrap", net === null && "hatch text-unknown")}>
                  {formatStubValue(net, "signed-money")}
                </span>
                {pay.target !== null && !isValue && (
                  <>
                    {" "}
                    <span className="whitespace-nowrap font-normal text-muted">of {formatMoneyCell(pay.target)}</span>
                  </>
                )}
              </span>
            </span>
            {!isValue && (
              <span className="mt-2.5 block">
                <Meter value={net} max={pay.target} label={`${month} target`} />
              </span>
            )}
            <span className="mt-1.5 block text-[0.8125rem] text-muted">{pace}</span>
          </span>
        }
      >
        <Stub label={`${month} ${isValue ? "value book" : "pay"} stub`} lines={payStubLines(pay, wholeUnknown)} />
        {beside && <Stub label={`${month} value book, realised`} lines={beside} />}
      </Disclosure>
      {noTarget && (
        <p className="mt-1.5 text-[0.8125rem]">
          <Link
            href="/more"
            className="inline-flex min-h-11 items-center font-semibold underline underline-offset-2 md:min-h-6"
          >
            Set a target in More
          </Link>
        </p>
      )}
      {valueOut && (
        <p className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.8125rem] text-muted">
          <StatusWord tone="flag">Value book unavailable</StatusWord>
          <span>
            {isValue
              ? "The value book could not be read, so there is no figure for this month."
              : "The value book could not be read, so its sales are not counted here."}
          </span>
        </p>
      )}
      {isValue && !valueOut && (pay.value_n_closed ?? 0) === 0 && (
        <p className="mt-3 text-[0.8125rem] text-muted">Nothing was sold from the value book in {month}.</p>
      )}
      {spreadsOut && (
        <p className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.8125rem] text-muted">
          <StatusWord tone="flag">Spreads unavailable</StatusWord>
          <span>
            {wholeUnknown
              ? "Spread income is unavailable because the spreads database could not be read."
              : "Spread income is unavailable because the spreads database could not be read, so this total leaves it out."}
          </span>
        </p>
      )}
    </Card>
  );
}
