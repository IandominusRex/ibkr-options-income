"use client";

import clsx from "clsx";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Card } from "@/components/ui/Card";
import { StatusWord } from "@/components/ui/StatusWord";
import { Stub, formatStubValue } from "@/components/ui/Stub";
import { TradeCard } from "@/features/home/TradeCard";
import { optionStatus } from "@/features/home/positions";
import { ApiError, apiFetch } from "@/lib/api";
import { formatMoneyCell } from "@/lib/money";
import { Headlines } from "./Headlines";
import { RollCard } from "./RollCard";
import { NameNotes } from "@/features/market/NameNotes";
import { UnderlyingChart } from "./UnderlyingChart";
import { chartLines, nowLines, openedOn, positionTitle, subline } from "./position";
import type { PositionDetail } from "./types";

const todayNewYork = () => new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" }).format(new Date());

function BackLink() {
  return (
    <Link href="/" className="inline-flex min-h-11 items-center gap-1 text-[0.8125rem] font-semibold text-muted hover:text-content md:min-h-8">
      <ChevronLeft size={16} aria-hidden="true" />
      Home
    </Link>
  );
}

function Shell({ children }: { children: ReactNode }) {
  return <div className="mx-auto max-w-[1200px] px-4 py-3 md:px-7 md:py-4">{children}</div>;
}

/** "Now": figures straight from the latest snapshot, plus how the stock stands against the strike. */
function NowCard({ d, lastClose }: { d: PositionDetail; lastClose: number | null }) {
  const lines = nowLines(d, lastClose);
  if (lines.length === 0) return null;
  return (
    <Card as="section" aria-labelledby="now-title">
      <h2 id="now-title" className="text-[1.0625rem] font-bold">
        Now
      </h2>
      <dl className="mt-1">
        {lines.map((l) => (
          <div key={l.label} className="flex items-baseline justify-between gap-3 border-t border-border py-2 text-sm first:border-t-0">
            <dt className="text-muted">{l.label}</dt>
            <dd
              className={clsx(
                "tabular text-right font-semibold",
                l.tone === "gain" && "text-gain",
                l.tone === "loss" && "text-loss",
                l.tone === "unknown" && "hatch text-unknown",
              )}
            >
              {l.value}
            </dd>
          </div>
        ))}
      </dl>
      {d.degraded && (
        <p className="mt-2 flex flex-wrap items-center gap-2 text-[0.8125rem] text-muted">
          <StatusWord tone="flag">Delayed</StatusWord>
          <span>The portfolio snapshot behind these figures is not the live one.</span>
        </p>
      )}
    </Card>
  );
}

/** Shares: what is held and what it cost, with the wheel's premium counted in. */
function SharesCard({ d }: { d: PositionDetail }) {
  const s = d.stock;
  if (!s) return null;
  const c = d.campaign;
  return (
    <>
      <Card as="section" aria-labelledby="shares-title">
        <h2 id="shares-title" className="text-[1.0625rem] font-bold">
          The shares
        </h2>
        <dl className="mt-1">
          {[
            ["Shares held", String(s.shares)],
            ["Average cost", formatMoneyCell(s.avg_cost)],
            s.adjusted_cost_basis !== null ? ["Adjusted cost (premium counted)", formatMoneyCell(s.adjusted_cost_basis)] : null,
            s.market_price !== null ? ["Last price", formatMoneyCell(s.market_price)] : null,
            ["Open P&L", formatStubValue(s.unrealized_pnl_adjusted ?? s.unrealized_pnl, "signed-money")],
          ]
            .filter((r): r is string[] => r !== null)
            .map(([label, value]) => (
              <div key={label} className="flex items-baseline justify-between gap-3 border-t border-border py-2 text-sm first:border-t-0">
                <dt className="text-muted">{label}</dt>
                <dd className="tabular text-right font-semibold">{value}</dd>
              </div>
            ))}
        </dl>
      </Card>
      {c && (
        <Card as="section" aria-labelledby="wheel-title">
          <h2 id="wheel-title" className="text-[1.0625rem] font-bold">
            The wheel on {d.underlying}
          </h2>
          <p className="mt-1 text-sm text-muted">
            {c.assigned ? "These shares came from an assigned put." : "An open wheel thread."} Figures are before commissions.
          </p>
          <Stub
            label={`${d.underlying} wheel premium`}
            lines={[
              { label: "Premium collected", value: c.total_premium_collected, format: "signed-money", explain: "Every option sold on this name in the thread." },
              { label: "Bought back", value: -c.total_debit_paid, format: "signed-money", explain: "What it cost to close or roll legs in the thread." },
              { label: "Net premium", value: c.net_premium, format: "signed-money", total: true },
            ]}
          />
        </Card>
      )}
    </>
  );
}

export function PositionPage({ underlying, slug }: { underlying: string; slug: string }) {
  const [lastClose, setLastClose] = useState<number | null>(null);
  const { data, isError, error } = useQuery({
    queryKey: ["position", underlying, slug],
    queryFn: () => apiFetch<PositionDetail>(`/portfolio/positions/${encodeURIComponent(underlying)}/${encodeURIComponent(slug)}`),
    refetchInterval: 60_000,
    // A 404 will not change in a minute; the others are worth another try.
    retry: (n, e) => !(e instanceof ApiError && e.status === 404) && n < 2,
  });

  if (isError && !data) {
    const missing = error instanceof ApiError && error.status === 404;
    return (
      <Shell>
        <BackLink />
        <h1 className="mt-2 text-2xl font-extrabold tracking-[-0.015em]">{underlying.toUpperCase()}</h1>
        <p className="mt-3 text-sm">
          {missing
            ? "There is no record of this position. It may have closed and left the book before it was ever recorded here."
            : "This position could not be loaded. Go back and open it again in a moment."}
        </p>
      </Shell>
    );
  }
  if (!data) {
    return (
      <Shell>
        <BackLink />
        <div role="status" aria-busy="true" aria-label="Loading the position">
          <div className="mt-2 h-8 w-56 rounded-xl bg-sunk" />
          <div className="mt-2 h-4 w-72 rounded bg-sunk" />
          <div className="mt-6 h-[240px] rounded-xl bg-sunk" />
        </div>
      </Shell>
    );
  }

  const today = todayNewYork();
  const status = data.option ? optionStatus(data.option, today) : null;
  const sub = subline(data);
  const symbol = data.underlying;

  return (
    <Shell>
      <BackLink />
      <header className="mt-1">
        <h1 className="text-2xl font-extrabold tracking-[-0.015em]">{positionTitle(data)}</h1>
        <p className="mt-1 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-sm text-muted">
          {status && <StatusWord tone={status.tone}>{status.word}</StatusWord>}
          {!data.held && <StatusWord tone="neutral">No longer held</StatusWord>}
          {sub && <span>{sub}</span>}
        </p>
      </header>

      {/* One grid, placed by CSS so the DOM order is the phone order: chart, the trade, headlines.
          From 1024px the chart and the headlines stack on the left and the trade column sits right. */}
      <div className="mt-4 grid items-start gap-x-6 gap-y-5 lg:grid-cols-[minmax(0,1fr)_340px] lg:grid-rows-[auto_1fr]">
        <div className="min-w-0 lg:col-start-1 lg:row-start-1">
          <UnderlyingChart symbol={symbol} lines={chartLines(data)} openedOn={openedOn(data)} onLastClose={setLastClose} />
        </div>

        <div className="grid gap-4 lg:col-start-2 lg:row-span-2 lg:row-start-1">
          {data.kind === "shares" ? (
            <SharesCard d={data} />
          ) : data.opened ? (
            <TradeCard trade={data.opened} when="date" heading="none" />
          ) : (
            <Card as="section" aria-labelledby="no-record-title">
              <h2 id="no-record-title" className="text-[1.0625rem] font-bold">
                The trade
              </h2>
              <p className="mt-1 text-sm text-muted">
                This position was not opened by the system, so there is no record of its premium or its reasons here.
              </p>
            </Card>
          )}
          {data.held ? <NowCard d={data} lastClose={lastClose} /> : data.closed && <TradeCard trade={data.closed} when="date" heading="none" />}
          {/* Only a held short option with a known contract can be rolled. */}
          {data.held && data.option?.short && typeof data.option.strike === "number" && data.option.right && (
            <RollCard
              underlying={data.underlying}
              symbol={data.option.symbol}
              strike={data.option.strike}
              right={data.option.right}
            />
          )}
          {data.kind === "spread" && !data.spreads_available && (
            <p className="text-[0.8125rem] text-muted">The spreads book could not be read, so this spread is incomplete.</p>
          )}
        </div>

        <div className="min-w-0 lg:col-start-1 lg:row-start-2">
          <Headlines symbol={symbol} />
          <div className="mt-5">
            <NameNotes symbol={symbol} />
          </div>
        </div>
      </div>
    </Shell>
  );
}
