"use client";

import { useQuery } from "@tanstack/react-query";
import { Card } from "@/components/ui/Card";
import { Meter } from "@/components/ui/Meter";
import { StatusWord } from "@/components/ui/StatusWord";
import { Stub, formatStubValue } from "@/components/ui/Stub";
import { payStubLines } from "@/features/home/PayCard";
import type { MonthPay, MonthPayResponse } from "@/features/home/types";
import { apiFetch } from "@/lib/api";
import { UNKNOWN } from "@/lib/format";
import { formatMoneyCell } from "@/lib/money";
import { MonthStepper } from "./MonthStepper";
import { monthLabel } from "./month";

/** The pace under the meter: against the target and, for this month only, the days left. */
function Pace({ pay, current }: { pay: MonthPay; current: boolean }) {
  const left = current ? ` · ${pay.days_left} ${pay.days_left === 1 ? "day" : "days"} left` : "";
  if (pay.target_mode === "off") return <>No target set{left}</>;
  if (pay.target === null) {
    // The setting is there; the account value at the month's start is not.
    return (
      <>
        Target <span className="hatch">{UNKNOWN}</span> · needs the month&apos;s opening account value{left}
      </>
    );
  }
  if (pay.progress_pct === null) {
    return (
      <>
        <span className="hatch">{UNKNOWN}</span> of target{left}
      </>
    );
  }
  return (
    <>
      {Math.round(Math.max(0, pay.progress_pct))}% of target{left}
    </>
  );
}

/**
 * One New York month as a stub, always open: the same lines as Home's pay card, over any month
 * from the one the system began to this one. The month is the page's (`?month=`); a month nothing
 * was opened or closed in shows its genuine zeros and says so.
 */
export function PayMonth({
  month,
  current,
  floor,
  onMonth,
}: {
  month: string;
  current: string;
  floor: string | null;
  onMonth: (month: string) => void;
}) {
  const label = monthLabel(month);
  const { data, isError } = useQuery({
    queryKey: ["pnl", "month", "all", month],
    queryFn: () => apiFetch<MonthPayResponse>(`/pnl/month?month=${month}&strategy=all`),
    placeholderData: (prev) => prev,
    refetchInterval: 60_000,
  });
  const pay = data?.pay;
  const isCurrent = month === current;
  const lines = pay
    ? payStubLines(pay).map((l) => (l.total && !isCurrent ? { ...l, label: "Net for the month" } : l))
    : [];

  return (
    <Card aria-labelledby="pay-title">
      <MonthStepper month={month} current={current} floor={floor} onChange={onMonth} />
      <div className="mt-3 flex flex-wrap items-baseline justify-between gap-x-2.5">
        <h2 id="pay-title" className="whitespace-nowrap text-[1.0625rem] font-bold">
          {label} pay
        </h2>
        {pay && (
          <span className="tabular ml-auto text-right font-mono font-semibold">
            <span className="whitespace-nowrap">{formatStubValue(pay.net, "signed-money")}</span>
            {pay.target !== null && (
              <>
                {" "}
                <span className="whitespace-nowrap font-normal text-muted">of {formatMoneyCell(pay.target)}</span>
              </>
            )}
          </span>
        )}
      </div>
      {isError && !data ? (
        <>
          <p className="mt-2 text-sm text-muted">Could not load this month&apos;s pay.</p>
          <p className="mt-1 text-[0.8125rem] text-muted">It tries again every minute.</p>
        </>
      ) : !pay ? (
        <div role="status" aria-busy="true" aria-label="Loading this month's pay" className="mt-3 h-24 rounded-xl bg-sunk" />
      ) : (
        <>
          <div className="mt-2.5">
            <Meter value={pay.net} max={pay.target} label={`${label} target`} />
          </div>
          <p className="mt-1.5 text-[0.8125rem] text-muted">
            <Pace pay={pay} current={isCurrent} />
          </p>
          <Stub label={`${label} pay stub`} lines={lines} />
          {pay.n_opened === 0 && pay.n_closed === 0 && (
            <p className="mt-2 text-[0.8125rem] text-muted">Nothing was opened or closed in {label}.</p>
          )}
          {data!.spreads_available === false && (
            <p className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.8125rem] text-muted">
              <StatusWord tone="flag">Spreads unavailable</StatusWord>
              <span>
                Spread income is unavailable because the spreads database could not be read, so this total leaves it
                out.
              </span>
            </p>
          )}
        </>
      )}
    </Card>
  );
}
