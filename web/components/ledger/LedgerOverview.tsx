"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Card } from "@/components/ui/Card";
import { apiFetch } from "@/lib/api";
import { MonthlyBars, PnlCurve } from "./Charts";
import { money, rate, signClass } from "./format";
import { OutcomePill } from "./OutcomePill";
import { TickerTable } from "./TickerTable";
import { Tile, TileList } from "./Tile";
import type { LedgerBucket, LedgerSummary, LedgerSummaryResponse, LedgerTickersResponse } from "./types";

const H2 = "text-[1.0625rem] font-bold";
const LINK = "inline-flex min-h-11 items-center font-semibold underline underline-offset-2 md:min-h-8";

function Tiles({ s }: { s: LedgerSummary }) {
  return (
    <TileList testId="ledger-tiles">
      <Tile id="total" label="Total profit" value={money(s.total_realized_usd)} tone={signClass(s.total_realized_usd)} />
      <Tile id="contributed" label="Contributed capital" value={money(s.contributed_usd)} />
      <Tile id="utilised" label="Capital utilised" value={money(s.capital_utilised_usd)} />
      <Tile id="available" label="Available capital" value={money(s.available_usd)} />
      <Tile id="unrealized" label="Unrealised" value={money(s.unrealized_usd)} tone={signClass(s.unrealized_usd)} />
      <Tile id="win-rate" label="Win rate" value={rate(s.win_rate)} />
      <Tile id="month" label="Premium this month" value={money(s.premium_this_month_usd)} />
    </TileList>
  );
}

function Buckets({ title, rows }: { title: string; rows: LedgerBucket[] }) {
  return (
    <Card as="section" aria-label={title} data-testid={`buckets-${title.split(" ")[1]}`}>
      <h2 className={H2}>{title}</h2>
      {rows.length === 0 ? (
        <p className="mt-2 text-sm text-muted">None yet.</p>
      ) : (
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-[0.8125rem]">
            <thead className="text-left text-xs font-semibold tracking-[0.04em] text-muted">
              <tr>
                <th className="py-1.5 pr-4 font-semibold">Group</th>
                <th className="py-1.5 pr-4 text-right font-semibold">Closed</th>
                <th className="py-1.5 pr-4 text-right font-semibold">Realised</th>
                <th className="py-1.5 pr-4 text-right font-semibold">Win rate</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((b) => (
                <tr key={b.label} className="border-t border-border">
                  <td className="py-2 pr-4">{b.label}</td>
                  <td className="tabular py-2 pr-4 text-right font-mono">{b.n_closed}</td>
                  <td className={`tabular py-2 pr-4 text-right font-mono ${signClass(b.realized_usd)}`}>
                    {money(b.realized_usd)}
                  </td>
                  <td className="tabular py-2 pr-4 text-right font-mono">{rate(b.win_rate)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

/**
 * The broker-truth ledger's overview, the Ledger view on Activity: what IBKR reports, built from
 * the live feed, the Flex query and statement imports, with the trades list, the ticker pages and
 * the statement import one link away. It has no sub-navigation of its own: those pages lead back
 * here.
 */
export function LedgerOverview() {
  const summary = useQuery({
    queryKey: ["ledger", "summary"],
    queryFn: () => apiFetch<LedgerSummaryResponse>("/ledger/summary"),
  });
  const tickers = useQuery({
    queryKey: ["ledger", "tickers"],
    queryFn: () => apiFetch<LedgerTickersResponse>("/ledger/tickers"),
  });
  const s = summary.data?.summary;

  return (
    <div className="grid grid-cols-1 gap-4" data-testid="ledger-overview">
      <div className="grid gap-1">
        <p className="text-[0.8125rem] text-muted">
          What IBKR reports, from the live feed, the Flex query and statement imports. It can differ from the
          system&apos;s own record under Pay.
        </p>
        <p className="flex flex-wrap gap-x-5 text-[0.8125rem]">
          <Link href="/ledger/trades" className={LINK}>
            All trades
          </Link>
          <Link href="/ledger/import" className={LINK}>
            Import a statement
          </Link>
        </p>
      </div>
      {summary.isError && <p className="text-sm text-muted">Could not load the ledger.</p>}
      {!s && !summary.isError && <p className="text-sm text-muted">Loading the ledger</p>}
      {s && (
        <>
          <Card as="section" aria-labelledby="ledger-totals">
            <h2 id="ledger-totals" className={H2}>
              Totals
            </h2>
            <Tiles s={s} />
            {s.orphan_closes > 0 && (
              <p className="mt-3 text-sm text-unknown">
                {s.orphan_closes} closing trades have no opening in the imported history. Import the earlier
                statement to complete them.
              </p>
            )}
            {s.fx_incomplete && (
              <p className="mt-3 text-sm text-unknown">
                Some non-USD figures have no FX rate yet and are left out of USD totals. A Flex pull fills them in.
              </p>
            )}
          </Card>
          <div className="grid items-start gap-4 lg:grid-cols-2">
            <Card as="section" aria-label="Cumulative realised P&L">
              <PnlCurve points={s.curve} />
              <p className="mt-1 text-xs text-muted" data-testid="curve-caption">
                Trading P&amp;L only. The Total profit tile also includes interest and fees.
              </p>
            </Card>
            <Card as="section" aria-label="Premium and realised by month">
              <MonthlyBars months={s.months} />
            </Card>
          </div>
          {(s.by_strategy.length > 0 || s.by_book.length > 0) && (
            <div className="grid items-start gap-4 md:grid-cols-2">
              <Buckets title="By strategy" rows={s.by_strategy} />
              <Buckets title="By book (wheel system, credit spreads, your own trades)" rows={s.by_book} />
            </div>
          )}
        </>
      )}
      <Card as="section" aria-labelledby="ledger-tickers">
        <h2 id="ledger-tickers" className={H2}>
          By ticker
        </h2>
        <div className="mt-2">
          {tickers.isError && <p className="text-sm text-muted">Could not load tickers.</p>}
          {tickers.isLoading && <p className="text-sm text-muted">Loading tickers</p>}
          {tickers.data && <TickerTable tickers={tickers.data.tickers} />}
        </div>
      </Card>
      {s && s.upcoming.length > 0 && (
        <Card as="section" aria-labelledby="ledger-upcoming">
          <h2 id="ledger-upcoming" className={H2}>
            Upcoming expiries
          </h2>
          <ul className="mt-1">
            {s.upcoming.map((t) => (
              <li
                key={t.order_key}
                className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-border py-2.5 text-sm first:border-t-0"
              >
                <span className="tabular font-mono text-muted">{t.expiry}</span>
                <Link href={`/ledger/ticker/${t.underlying}`} className="font-mono font-semibold hover:underline">
                  {t.underlying}
                </Link>
                <span className="tabular font-mono">
                  {t.side} {t.lots} x {t.strike}
                  {t.right}
                </span>
                <OutcomePill outcome={t.outcome} overridden={t.outcome_overridden} />
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
