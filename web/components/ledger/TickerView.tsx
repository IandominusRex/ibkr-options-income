"use client";

import { useQuery } from "@tanstack/react-query";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ApiError, apiFetch } from "@/lib/api";
import { money, pct, rate, signClass } from "./format";
import { LedgerNav } from "./LedgerNav";
import { Tile } from "./Tile";
import { TradesView } from "./TradesView";
import type { LedgerTickerResponse } from "./types";

export function TickerView({ symbol }: { symbol: string }) {
  const upper = symbol.toUpperCase();
  const { data, error } = useQuery({
    queryKey: ["ledger", "ticker", upper],
    queryFn: () => apiFetch<LedgerTickerResponse>(`/ledger/tickers/${upper}`),
    retry: false,
  });

  if (error instanceof ApiError && error.status === 404) {
    return (<div className="space-y-4"><LedgerNav /><p className="text-sm text-muted">No ledger history for {upper}.</p></div>);
  }
  if (error) return <p className="text-sm text-muted">Could not load {upper}.</p>;
  if (!data) return <p className="text-sm text-muted">Loading {upper}</p>;

  const d = data.detail;
  const t = d.ticker;
  return (
    <div className="space-y-6" data-testid="ticker-view">
      <LedgerNav />
      <h1 className="font-mono text-xl text-content">{t.symbol}</h1>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-8">
        <Tile id="total" label="Total realised" value={money(t.total_realized, t.currency)} tone={signClass(t.total_realized)} />
        <Tile id="options" label="Options net" value={money(t.option_net_pnl, t.currency)} />
        <Tile id="stock" label="Stock realised" value={money(t.stock_realized, t.currency)} />
        <Tile id="dividends" label="Dividends net" value={money(t.dividends_net, t.currency)} />
        <Tile id="unrealized" label="Unrealised" value={money(t.unrealized, t.currency)} tone={signClass(t.unrealized)} />
        <Tile id="win-rate" label="Win rate" value={rate(t.win_rate)} />
        <Tile id="broker-cost" label="Broker avg cost" value={money(t.broker_avg_cost, t.currency)} />
        <Tile id="wheel-basis" label="Wheel-adjusted basis" value={money(t.wheel_adjusted_basis, t.currency)} />
      </div>
      <p className="text-xs text-muted">
        {t.n_trades} trades, {t.n_open} open. Annualised return on capital-days {pct(t.annualised_return_pct)}. Shares held {t.shares_held}.
      </p>

      {d.basis_walk.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-sm text-content">Cost-basis walk</h2>
          <figure className="h-56" aria-label="Wheel-adjusted cost basis per share">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={d.basis_walk}>
                <XAxis dataKey="point_date" tick={{ fill: "var(--color-muted)", fontSize: 11 }} />
                <YAxis domain={["auto", "auto"]} tick={{ fill: "var(--color-muted)", fontSize: 11 }} width={60} />
                <Tooltip formatter={(v) => money(Number(v), t.currency)} labelFormatter={(_, p) => p?.[0]?.payload?.label ?? ""} />
                <Line type="stepAfter" dataKey="basis_per_share" stroke="var(--color-focus)" isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </figure>
          <ol className="space-y-1 text-xs text-muted">
            {d.basis_walk.map((p, i) => (
              <li key={i} className="tabular">{p.point_date} {p.label}: {money(p.basis_per_share, t.currency)}</li>
            ))}
          </ol>
        </section>
      )}

      {d.lots.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-sm text-content">Share lots</h2>
          <table className="w-full text-sm">
            <thead className="text-left text-muted"><tr><th className="py-1 pr-4">Acquired</th><th className="py-1 pr-4">How</th><th className="py-1 pr-4 text-right">Qty</th><th className="py-1 pr-4 text-right">Remaining</th><th className="py-1 pr-4 text-right">Cost/share</th></tr></thead>
            <tbody>
              {d.lots.map((l) => (
                <tr key={l.lot_key} className="border-t border-border">
                  <td className="tabular py-1 pr-4">{l.acquired_date}</td><td className="py-1 pr-4">{l.source}</td>
                  <td className="tabular py-1 pr-4 text-right">{l.quantity}</td><td className="tabular py-1 pr-4 text-right">{l.remaining}</td>
                  <td className="tabular py-1 pr-4 text-right">{money(l.cost_per_share, l.currency)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {d.dividends.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-sm text-content">Dividends and withholding</h2>
          <ul className="space-y-1 text-sm">
            {d.dividends.map((c, i) => (
              <li key={i} className="tabular"><span className="text-muted">{c.event_date}</span> <span className={signClass(c.amount)}>{money(c.amount, c.currency)}</span> <span className="text-muted">{c.event_type}</span></li>
            ))}
          </ul>
        </section>
      )}

      <section className="space-y-2">
        <h2 className="text-sm text-content">Every trade</h2>
        <TradesView fixedSymbol={upper} />
      </section>
    </div>
  );
}
