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

const ACCOUNT: { key: keyof Omit<AccountBlock, "as_of">; label: string }[] = [
  { key: "net_liquidation", label: "Net liquidation" },
  { key: "total_cash", label: "Total cash" },
  { key: "buying_power", label: "Buying power" },
  { key: "maintenance_margin", label: "Maintenance margin" },
  { key: "excess_liquidity", label: "Excess liquidity" },
];

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

function exposureRows(e: ExposureBlock): FigureRow[] {
  const pct = e.buying_power_utilisation_pct;
  const unknownPct = pct === null || pct === undefined;
  return [
    { label: "Open positions", value: String(e.open_positions) },
    { label: "Open shorts", value: String(e.open_shorts) },
    { label: "Open campaigns", value: String(e.open_campaigns) },
    { label: "Shorts at assignment risk", value: String(e.shorts_at_assignment_risk) },
    { label: "Net delta exposure", value: signed(e.net_delta_exposure) },
    { label: "Cash secured against puts", value: formatMoneyCell(e.cash_secured_against_puts) },
    { label: "Buying power used", value: unknownPct ? UNKNOWN : `${pct.toFixed(1)}%`, unknown: unknownPct },
  ];
}

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
      <Card as="div" className="h-[168px]" role="status" aria-busy="true" aria-label="Loading the account summary" />
    );
  }

  const none = data.source === "none";
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
          <div className="grid gap-x-8 sm:grid-cols-2">
            {data.account && (
              <FigureLines
                label="Account figures"
                rows={ACCOUNT.map(({ key, label }) => moneyRow(label, data.account![key] as SourcedFloat))}
              />
            )}
            {data.exposure && <FigureLines label="Exposure figures" rows={exposureRows(data.exposure)} />}
          </div>
        </>
      )}
    </Card>
  );
}
