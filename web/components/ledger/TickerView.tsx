"use client";

import { useQuery } from "@tanstack/react-query";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card } from "@/components/ui/Card";
import { ApiError, apiFetch } from "@/lib/api";
import { BackToLedger } from "./BackToLedger";
import { money, pct, rate, signClass } from "./format";
import { Tile, TileList } from "./Tile";
import { TradesView } from "./TradesView";
import type { LedgerTickerResponse } from "./types";

const H2 = "text-[1.0625rem] font-bold";
const TH = "py-1.5 pr-4 font-semibold";

export function TickerView({ symbol }: { symbol: string }) {
  const upper = symbol.toUpperCase();
  const { data, error } = useQuery({
    queryKey: ["ledger", "ticker", upper],
    queryFn: () => apiFetch<LedgerTickerResponse>(`/ledger/tickers/${upper}`),
    retry: false,
  });

  if (error instanceof ApiError && error.status === 404) {
    return (
      <div className="grid gap-3">
        <BackToLedger />
        <p className="text-sm text-muted">No ledger history for {upper}.</p>
      </div>
    );
  }
  if (error) {
    return (
      <div className="grid gap-3">
        <BackToLedger />
        <p className="text-sm text-muted">Could not load {upper}.</p>
      </div>
    );
  }
  if (!data) return <p className="text-sm text-muted">Loading {upper}</p>;

  const d = data.detail;
  const t = d.ticker;
  return (
    <div className="grid grid-cols-1 gap-4" data-testid="ticker-view">
      <div className="grid gap-1">
        <BackToLedger />
        <h1 className="font-mono text-2xl font-extrabold tracking-[-0.015em]">{t.symbol}</h1>
      </div>
      <Card as="section" aria-label={`${t.symbol} figures`}>
        <TileList>
          <Tile id="total" label="Total realised" value={money(t.total_realized, t.currency)} tone={signClass(t.total_realized)} />
          <Tile id="options" label="Options net" value={money(t.option_net_pnl, t.currency)} />
          <Tile id="stock" label="Stock realised" value={money(t.stock_realized, t.currency)} />
          <Tile id="dividends" label="Dividends net" value={money(t.dividends_net, t.currency)} />
          <Tile id="unrealized" label="Unrealised" value={money(t.unrealized, t.currency)} tone={signClass(t.unrealized)} />
          <Tile id="win-rate" label="Win rate" value={rate(t.win_rate)} />
          <Tile id="broker-cost" label="Broker avg cost" value={money(t.broker_avg_cost, t.currency)} />
          <Tile id="wheel-basis" label="Wheel-adjusted basis" value={money(t.wheel_adjusted_basis, t.currency)} />
        </TileList>
        <p className="mt-3 text-xs text-muted">
          {t.n_trades} trades, {t.n_open} open. Annualised return on capital-days {pct(t.annualised_return_pct)}. Shares held {t.shares_held}.
        </p>
      </Card>

      {d.basis_walk.length > 0 && (
        <Card as="section" aria-labelledby="basis-walk">
          <h2 id="basis-walk" className={H2}>
            Cost-basis walk
          </h2>
          <figure className="mt-2 h-56" aria-label="Wheel-adjusted cost basis per share">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={d.basis_walk}>
                <XAxis dataKey="point_date" tick={{ fill: "var(--color-muted)", fontSize: 11 }} />
                <YAxis domain={["auto", "auto"]} tick={{ fill: "var(--color-muted)", fontSize: 11 }} width={60} />
                <Tooltip formatter={(v) => money(Number(v), t.currency)} labelFormatter={(_, p) => p?.[0]?.payload?.label ?? ""} />
                <Line type="stepAfter" dataKey="basis_per_share" stroke="var(--chart-line)" isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </figure>
          <ol className="tabular mt-2 font-mono text-xs text-muted">
            {d.basis_walk.map((p, i) => (
              <li key={i} className="border-t border-border py-1.5 first:border-t-0">
                {p.point_date} {p.label}: {money(p.basis_per_share, t.currency)}
              </li>
            ))}
          </ol>
        </Card>
      )}

      {d.lots.length > 0 && (
        <Card as="section" aria-labelledby="share-lots">
          <h2 id="share-lots" className={H2}>
            Share lots
          </h2>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full text-[0.8125rem]">
              <thead className="text-left text-xs font-semibold tracking-[0.04em] text-muted">
                <tr>
                  <th className={TH}>Acquired</th>
                  <th className={TH}>How</th>
                  <th className={`${TH} text-right`}>Qty</th>
                  <th className={`${TH} text-right`}>Remaining</th>
                  <th className={`${TH} text-right`}>Cost/share</th>
                </tr>
              </thead>
              <tbody>
                {d.lots.map((l) => (
                  <tr key={l.lot_key} className="border-t border-border">
                    <td className="tabular py-2 pr-4 font-mono">{l.acquired_date}</td>
                    <td className="py-2 pr-4">{l.source}</td>
                    <td className="tabular py-2 pr-4 text-right font-mono">{l.quantity}</td>
                    <td className="tabular py-2 pr-4 text-right font-mono">{l.remaining}</td>
                    <td className="tabular py-2 pr-4 text-right font-mono">{money(l.cost_per_share, l.currency)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {d.dividends.length > 0 && (
        <Card as="section" aria-labelledby="dividends">
          <h2 id="dividends" className={H2}>
            Dividends and withholding
          </h2>
          <ul className="mt-1 text-sm">
            {d.dividends.map((c, i) => (
              <li key={i} className="tabular flex flex-wrap gap-x-3 border-t border-border py-2 first:border-t-0">
                <span className="font-mono text-muted">{c.event_date}</span>
                <span className={`font-mono ${signClass(c.amount)}`}>{money(c.amount, c.currency)}</span>
                <span className="text-muted">{c.event_type}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <section className="grid gap-2">
        <h2 className={H2}>Every trade</h2>
        <TradesView fixedSymbol={upper} />
      </section>
    </div>
  );
}
