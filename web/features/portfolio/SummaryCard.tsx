"use client";

import { useQuery } from "@tanstack/react-query";
import { DegradedNotice } from "@/components/portfolio/DegradedNotice";
import { FreshnessLabel } from "@/components/portfolio/FreshnessLabel";
import type {
  AccountBlock,
  ExposureBlock,
  PortfolioSummaryResponse,
  SourcedFloat,
} from "@/components/portfolio/types";
import { Card } from "@/components/ui/Card";
import { StatusWord } from "@/components/ui/StatusWord";
import { FigureLines, type FigureRow } from "@/features/claude-context/FigureLines";
import { FRESH_FOR_MINUTES } from "@/features/home/positions";
import { apiFetch } from "@/lib/api";
import { UNKNOWN } from "@/lib/format";
import { formatMoneyCell, isStale } from "@/lib/money";
import { AccountDonut } from "./AccountDonut";
import { cashPct } from "./donut";

function moneyRow(label: string, f: SourcedFloat): FigureRow {
  const unknown = f.value === null || f.value === undefined;
  return {
    label,
    unknown,
    value: unknown ? (
      UNKNOWN
    ) : (
      <>
        {formatMoneyCell(f.value)}
        {f.stale && <span className="ml-1.5 font-sans text-xs font-normal text-muted">stale</span>}
      </>
    ),
  };
}

/** A real minus for a negative figure, as the stub writes signed money. */
function signed(n: number): string {
  const body = Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: 1 });
  return n > 0 ? `+${body}` : n < 0 ? `−${body}` : body;
}

/** The lines under the donut: what margin leaves, then what the book holds. */
function marginRows(a: AccountBlock | null | undefined, e: ExposureBlock | null | undefined): FigureRow[] {
  const rows: FigureRow[] = [];
  if (a) {
    rows.push(moneyRow("Maintenance margin", a.maintenance_margin), moneyRow("Excess liquidity", a.excess_liquidity));
  }
  if (e) {
    rows.push(
      { label: "Shorts at assignment risk", value: String(e.shorts_at_assignment_risk) },
      { label: "Net delta exposure", value: signed(e.net_delta_exposure) },
    );
  }
  return rows;
}

function bookRows(e: ExposureBlock): FigureRow[] {
  return [
    { label: "Open positions", value: String(e.open_positions) },
    { label: "Open shorts", value: String(e.open_shorts) },
    { label: "Open campaigns", value: String(e.open_campaigns) },
  ];
}

const known = (f: SourcedFloat | undefined): number | null => (f && f.value !== null && f.value !== undefined ? f.value : null);

/**
 * The Account card: how old the portfolio reading is, in words, and what it says. Every figure
 * is a Sourced value, so an unknown one is a hatched n/a and a stale one says so. The "Delayed"
 * word and the age follow Home's positions card (older than 30 minutes, or degraded); the API's
 * degraded note is shown verbatim, never paraphrased.
 */
export function SummaryCard() {
  const { data, isError } = useQuery({
    queryKey: ["portfolio", "summary"],
    queryFn: () => apiFetch<PortfolioSummaryResponse>("/portfolio/summary"),
    placeholderData: (prev) => prev,
    refetchInterval: 30_000,
  });

  if (isError && !data) {
    return (
      <Card aria-labelledby="account-title">
        <h2 id="account-title" className="text-[1.0625rem] font-bold">
          Account
        </h2>
        <p className="mt-2 text-sm text-muted">Could not load the account summary.</p>
        <p className="mt-1 text-[0.8125rem] text-muted">It tries again every 30 seconds.</p>
      </Card>
    );
  }
  if (!data) {
    return (
      <Card as="div" className="h-[440px] sm:h-[400px]" role="status" aria-busy="true" aria-label="Loading the account summary" />
    );
  }

  const none = data.source === "none";
  const netLiq = known(data.account?.net_liquidation);
  const cashValue = known(data.account?.total_cash);
  const buyingPower = known(data.account?.buying_power);
  const secured = data.exposure ? data.exposure.cash_secured_against_puts : null;
  const usedPct = data.exposure?.buying_power_utilisation_pct ?? null;
  const cash = cashPct(cashValue, netLiq);
  const delayed = !none && (data.degraded || isStale(data.as_of, FRESH_FOR_MINUTES));

  return (
    <Card aria-labelledby="account-title">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h2 id="account-title" className="text-[1.0625rem] font-bold">
          Account
        </h2>
        {!none && (
          <span className="flex flex-wrap items-center gap-2 text-[0.8125rem] text-muted">
            {delayed && <StatusWord tone="flag">Delayed</StatusWord>}
            <span>
              Updated <FreshnessLabel asOf={data.as_of} freshForMinutes={FRESH_FOR_MINUTES} />
            </span>
          </span>
        )}
      </div>
      {none ? (
        <p className="mt-2 text-sm">{data.note ?? "No portfolio snapshot has been captured yet."}</p>
      ) : (
        <>
          {data.degraded && data.note && (
            <div className="mt-2.5">
              <DegradedNotice note={data.note} />
            </div>
          )}
          <div className="mt-4">
            <AccountDonut
              netLiq={netLiq}
              netLiqStale={data.account?.net_liquidation.stale === true}
              usedPct={usedPct}
              cashPct={cash}
              usedSum={
                secured !== null && buyingPower !== null
                  ? `${formatMoneyCell(secured)} secured against puts, of ${formatMoneyCell(buyingPower)} buying power`
                  : null
              }
              cashSum={
                cashValue !== null && netLiq !== null
                  ? `${formatMoneyCell(cashValue)} of ${formatMoneyCell(netLiq)} net liquidation`
                  : null
              }
            />
          </div>
          <div className="grid gap-x-8 sm:grid-cols-2">
            {(data.account || data.exposure) && (
              <FigureLines label="Margin and risk figures" rows={marginRows(data.account, data.exposure)} />
            )}
            {data.exposure && <FigureLines label="Book figures" rows={bookRows(data.exposure)} />}
          </div>
        </>
      )}
    </Card>
  );
}
