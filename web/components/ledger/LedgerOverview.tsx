"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { MonthlyBars, PnlCurve } from "./Charts";
import { money, rate, signClass } from "./format";
import { LedgerNav } from "./LedgerNav";
import { OutcomePill } from "./OutcomePill";
import { Tile } from "./Tile";
import { TickerTable } from "./TickerTable";
import type { LedgerBucket, LedgerSummary, LedgerSummaryResponse, LedgerTickersResponse } from "./types";

function Tiles({ s }: { s: LedgerSummary }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-7" data-testid="ledger-tiles">
      <Tile id="total" label="Total profit" value={money(s.total_realized_usd)} tone={signClass(s.total_realized_usd)} />
      <Tile id="contributed" label="Contributed capital" value={money(s.contributed_usd)} />
      <Tile id="utilised" label="Capital utilised" value={money(s.capital_utilised_usd)} />
      <Tile id="available" label="Available capital" value={money(s.available_usd)} />
      <Tile id="unrealized" label="Unrealised" value={money(s.unrealized_usd)} tone={signClass(s.unrealized_usd)} />
      <Tile id="win-rate" label="Win rate" value={rate(s.win_rate)} />
      <Tile id="month" label="Premium this month" value={money(s.premium_this_month_usd)} />
    </div>
  );
}

function Buckets({ title, rows }: { title: string; rows: LedgerBucket[] }) {
  return (
    <section className="space-y-2" data-testid={`buckets-${title.split(" ")[1]}`}>
      <h2 className="text-sm font-medium text-content">{title}</h2>
      <table className="w-full text-sm">
        <thead className="text-left text-muted">
          <tr><th className="py-1 pr-4">Group</th><th className="py-1 pr-4 text-right">Closed</th><th className="py-1 pr-4 text-right">Realised</th><th className="py-1 pr-4 text-right">Win rate</th></tr>
        </thead>
        <tbody>
          {rows.map((b) => (
            <tr key={b.label} className="border-t border-border">
              <td className="py-1 pr-4">{b.label}</td>
              <td className="tabular py-1 pr-4 text-right">{b.n_closed}</td>
              <td className={`tabular py-1 pr-4 text-right ${signClass(b.realized_usd)}`}>{money(b.realized_usd)}</td>
              <td className="tabular py-1 pr-4 text-right">{rate(b.win_rate)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

export function LedgerOverview() {
  const summary = useQuery({
    queryKey: ["ledger", "summary"],
    queryFn: () => apiFetch<LedgerSummaryResponse>("/ledger/summary"),
  });
  const tickers = useQuery({
    queryKey: ["ledger", "tickers"],
    queryFn: () => apiFetch<LedgerTickersResponse>("/ledger/tickers"),
  });

  return (
    <div className="space-y-6" data-testid="ledger-overview">
      <LedgerNav />
      {summary.isError && <p className="text-sm text-muted">Could not load the ledger.</p>}
      {!summary.data && !summary.isError && <p className="text-sm text-muted">Loading the ledger</p>}
      {summary.data && (
        <>
          <Tiles s={summary.data.summary} />
          {summary.data.summary.orphan_closes > 0 && (
            <p className="text-sm text-unknown">
              {summary.data.summary.orphan_closes} closing trades have no opening in the imported
              history. Import the earlier statement to complete them.
            </p>
          )}
          {summary.data.summary.fx_incomplete && (
            <p className="text-sm text-unknown">
              Some non-USD figures have no FX rate yet and are left out of USD totals. A Flex pull fills them in.
            </p>
          )}
          <div className="grid gap-6 lg:grid-cols-2">
            <div className="space-y-1">
              <PnlCurve points={summary.data.summary.curve} />
              <p className="text-xs text-muted" data-testid="curve-caption">
                Trading P&amp;L only. The Total profit tile also includes interest and fees.
              </p>
            </div>
            <MonthlyBars months={summary.data.summary.months} />
          </div>
        </>
      )}
      {summary.data && (summary.data.summary.by_strategy.length > 0 || summary.data.summary.by_book.length > 0) && (
        <div className="grid gap-6 md:grid-cols-2">
          <Buckets title="By strategy" rows={summary.data.summary.by_strategy} />
          <Buckets title="By book (system vs your own trades)" rows={summary.data.summary.by_book} />
        </div>
      )}
      <section className="space-y-2">
        <h2 className="text-sm font-medium text-content">By ticker</h2>
        {tickers.isError && <p className="text-sm text-muted">Could not load tickers.</p>}
        {tickers.isLoading && <p className="text-sm text-muted">Loading tickers</p>}
        {tickers.data && <TickerTable tickers={tickers.data.tickers} />}
      </section>
      {summary.data && summary.data.summary.upcoming.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-sm font-medium text-content">Upcoming expiries</h2>
          <ul className="space-y-1 text-sm">
            {summary.data.summary.upcoming.map((t) => (
              <li key={t.order_key} className="flex flex-wrap items-center gap-3">
                <span className="tabular text-muted">{t.expiry}</span>
                <Link href={`/ledger/ticker/${t.underlying}`} className="font-mono text-content hover:underline">{t.underlying}</Link>
                <span className="tabular">{t.side} {t.lots} x {t.strike}{t.right}</span>
                <OutcomePill outcome={t.outcome} overridden={t.outcome_overridden} />
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
